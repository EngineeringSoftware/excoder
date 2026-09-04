package org.throwgen.core;

import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.stmt.ThrowStmt;
import com.github.javaparser.ast.visitor.ModifierVisitor;
import com.github.javaparser.ast.visitor.Visitable;
import java.io.FileReader;
import java.io.FileWriter;
import java.io.IOException;

class BlockCleaner extends ThrowRemover {
    public Visitable visit(BlockStmt n, Void arg) {
        if (n.getStatements().size() == 1) {
            if (n.getParentNode().isPresent()) {
                try {
                    replaceStmt(n, n.getStatements().get(0));
                    return n.getStatements().get(0);
                } catch (ClassCastException cce) {
                    System.out.println(cce);
                }
            }
        }
        return super.visit(n, arg);
    }
}

class AllThrowCleaner extends ThrowRemover {
    public Visitable visit(ThrowStmt n, Void arg) {
        System.out.println("![rest-throw]!");
        return null;
    }
}

public class ThrowRemover extends ModifierVisitor<Void> {
    public void removeStmt(Node n) {
        if (!n.remove()) {
            throw new RuntimeException("Filed to remove node");
        }
    }

    public void replaceStmt(Node oldNode, Node newNode) {
        if (!oldNode.replace(newNode)) {
            throw new RuntimeException("Filed to replace node");
        }
    }

    public void takeStmtOut(NodeList<Statement> srcStmtList, BlockStmt des,
                            int startIdx) {
        int currIdx = startIdx;
        for (Statement statement : srcStmtList) {
            des.getStatements().add(currIdx++, statement);
        }
    }

    public void takeStmtOut(BlockStmt src, BlockStmt des, int startIdx) {
        takeStmtOut(src.getStatements(), des, startIdx);
    }

    public static void main(String[] args) throws IOException {
        if (args.length < 1) {
            System.out.println("Please provide the path to the Java file.");
            return;
        }
        FileReader inputFile = new FileReader(args[0]);
        CompilationUnit cu = StaticJavaParser.parse(inputFile);
        // MethodDeclaration mut = cu.findFirst(MethodDeclaration.class).get();
        cu.accept(new BlockCleaner(), null);
        cu.accept(new IfThrowRemover(), null);
        cu.accept(new CatchThrowRemover(), null);
        cu.accept(new SwitchThrowRemover(), null);
        cu.accept(new AllThrowCleaner(), null);

        FileWriter outFile = new FileWriter(args[1]);
        outFile.write(cu.toString());
        outFile.close();
    }
}
