package org.throwgen.core;

import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.CatchClause;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.stmt.TryStmt;
import com.github.javaparser.ast.visitor.Visitable;
import java.util.List;

public class CatchThrowRemover extends ThrowRemover {
    public Visitable visit(CatchClause n, Void arg) {
        List<Statement> cBlockStatements = n.getBody().getStatements();
        Boolean haveThrow = false;
        for (Statement cbStmt : cBlockStatements) {
            // if one of the statement in catch body is throw then remove
            // catch
            if (cbStmt.isThrowStmt()) {
                System.out.println("![catch-throw]!");
                haveThrow = true;
                break;
            }
        }
        if (haveThrow)
            return null;
        return super.visit(n, arg);
    }

    public Visitable visit(TryStmt n, Void arg) {
        n = (TryStmt)super.visit(n, arg);
        Statement out = n;
        if (n.getCatchClauses().size() == 0) {
            // if all catch is removed then remove the whole try stmt
            // move the try block and finally block outside
            Node tryParent = out.getParentNode().get();
            if (tryParent instanceof BlockStmt) {
                // take out anything in block stmt
                int start = ((BlockStmt)tryParent)
                                .asBlockStmt()
                                .getStatements()
                                .indexOf(n);
                takeStmtOut(n.getTryBlock(), (BlockStmt)tryParent, start);
                // deal with finally block
                if (n.getFinallyBlock().isPresent()) {
                    int startFinally =
                        start + n.getTryBlock().getStatements().size();
                    takeStmtOut(n.getFinallyBlock().get(), (BlockStmt)tryParent,
                                startFinally);
                }
                out = null;
            } else {
                BlockStmt outBlock = n.getTryBlock();
                if (n.getFinallyBlock().isPresent()) {
                    BlockStmt finallyBlock = n.getFinallyBlock().get();
                    outBlock.getStatements().addAll(
                        finallyBlock.getStatements());
                }
                out = outBlock;
            }
        }
        return out;
    }
}
