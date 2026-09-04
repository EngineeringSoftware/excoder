package org.throwgen.core;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.CompactConstructorDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.visitor.VoidVisitorAdapter;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

import org.json.simple.JSONObject;

public class ClassDataCollector extends VoidVisitorAdapter<Void> {
    private List<String> publicVariables = new ArrayList<>();
    private List<String> publicMethods = new ArrayList<>();
    private List<String> privateVariables = new ArrayList<>();
    private List<String> privateMethods = new ArrayList<>();
    private List<String> protectedVariables = new ArrayList<>();
    private List<String> protectedMethods = new ArrayList<>();
    private List<String> publicConstructors = new ArrayList<>();
    private String targetClassName;

    public ClassDataCollector(String name) { this.targetClassName = name; }

    @Override
    public void visit(FieldDeclaration field, Void arg) {
        if (checkClass(field)) {
            if (field.isPublic()) {
                publicVariables.add(field.toString());
            }else if(field.isPrivate()){
                privateVariables.add(field.toString());
            }else if (field.isProtected()){
                protectedVariables.add(field.toString());
            }
        }
        super.visit(field, arg);
    }

    @Override
    public void visit(MethodDeclaration method, Void arg) {
        if (checkClass(method)) {
            if (method.isPublic()) {
                publicMethods.add(method.getDeclarationAsString());
            }else if(method.isPrivate()){
                privateMethods.add(method.getDeclarationAsString());
            }else if (method.isProtected()){
                protectedMethods.add(method.getDeclarationAsString());
            }
        }
        super.visit(method, arg);
    }

    @Override
    public void visit(ConstructorDeclaration constructor, Void arg) {
        if (checkClass(constructor)) {
            publicConstructors.add(
                constructor.getDeclarationAsString(true, true, true));
        }
        super.visit(constructor, arg);
    }

    @Override
    public void visit(CompactConstructorDeclaration constructor, Void arg) {
        if (checkClass(constructor)) {
            publicConstructors.add(
                constructor.getDeclarationAsString(true, true, true));
        }
        super.visit(constructor, arg);
    }

    public boolean checkClass(Node node) {
        if (node.getParentNode().isPresent() &&
            node.getParentNode().get() instanceof ClassOrInterfaceDeclaration) {
            ClassOrInterfaceDeclaration classNode =
                (ClassOrInterfaceDeclaration)node.getParentNode().get();
            System.out.println(classNode.getNameAsString());
            return classNode.getNameAsString().equals(targetClassName);
        }
        return false;
    }

    public JSONObject asJson() {
        JSONObject out = new JSONObject();
        out.put("public_variables", publicVariables);
        out.put("private_variables", privateVariables);
        out.put("protected_variables", protectedVariables);
        out.put("public_methods", publicMethods);
        out.put("private_methods", privateMethods);
        out.put("protected_methods", protectedMethods);
        out.put("public_constructors", publicConstructors);

        return out;
    }

    public static void main(String[] args) throws IOException {
        if (args.length < 1) {
            System.err.println("Please provide the path to the Java file.");
            return;
        } else if (args.length < 2) {
            System.err.println("Please provide the path to the output file.");
            return;
        }

        FileReader inputFile = new FileReader(args[0]);
        CompilationUnit cu = StaticJavaParser.parse(inputFile);

        ClassDataCollector cdc = new ClassDataCollector(args[2]);
        cdc.visit(cu, null);

        FileWriter outFile = new FileWriter(args[1]);
        JSONObject out = cdc.asJson();
        out.put("_debug", String.format("%s %s %s", args[0], args[1], args[2]));
        outFile.write(out.toJSONString());
        outFile.close();
    }
}
